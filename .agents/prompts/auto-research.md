# autoresearch 
我希望能够优化当前 restyle 这个流程中(first run)的prompt(流程内置Prompt+DDI Style的Prompt)，
进而优化该流程产出slide能具备高稳定性，高一致性，高度匹配DDI Style，高质量的Slide。

如果要对这个需求做autoresearch, 你能为我做哪些事，我还需要提供哪些信息呢？

环境方面： 
- 我们会固定使用Gemini 的image生成功能。你在查阅代码时只需要关注这个模型链路即可


我当前的想法是:
1. 你先看一下代码，把restyle 过程执行的动作的prompt先抽取出来
  - 代码里封装的Prompt部分
  - ddi style提供的Prompt部分
  - ddi style 提供的ref image
2. 针对当前调用request时执行的动作代码，分两种方式来eval: 
  - 当前实现的restyle first run 的组装prompt的方式
  - 参考restyle流程中edit image的实现方式，通过conversation的方式组装request
    
3. 调整prompt，微调prompt，对比生成后的图片质量(可能每次要跑5-6个slide，查阅新旧slide 结合我们的reference image)。
